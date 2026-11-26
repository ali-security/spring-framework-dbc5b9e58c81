/*
 * Copyright 2002-2024 the original author or authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.springframework.web.accept;

import java.util.Collections;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import org.springframework.http.MediaType;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.context.request.ServletWebRequest;
import org.springframework.web.testfixture.servlet.MockHttpServletRequest;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * A test fixture with a test subclass of AbstractMappingContentNegotiationStrategy.
 *
 * @author Rossen Stoyanchev
 * @since 3.2
 */
class MappingContentNegotiationStrategyTests {

	@Test
	void resolveMediaTypes() throws Exception {
		Map<String, MediaType> mapping = Collections.singletonMap("json", MediaType.APPLICATION_JSON);
		TestMappingContentNegotiationStrategy strategy = new TestMappingContentNegotiationStrategy("json", mapping);

		List<MediaType> mediaTypes = strategy.resolveMediaTypes(null);

		assertThat(mediaTypes).hasSize(1);
		assertThat(mediaTypes.get(0).toString()).isEqualTo("application/json");
	}

	@Test
	void resolveMediaTypesNoMatch() throws Exception {
		Map<String, MediaType> mapping = null;
		TestMappingContentNegotiationStrategy strategy = new TestMappingContentNegotiationStrategy("blah", mapping);

		List<MediaType> mediaTypes = strategy.resolveMediaTypes(null);

		assertThat(mediaTypes).isEqualTo(ContentNegotiationStrategy.MEDIA_TYPE_ALL_LIST);
	}

	@Test
	void resolveMediaTypesNoKey() throws Exception {
		Map<String, MediaType> mapping = Collections.singletonMap("json", MediaType.APPLICATION_JSON);
		TestMappingContentNegotiationStrategy strategy = new TestMappingContentNegotiationStrategy(null, mapping);

		List<MediaType> mediaTypes = strategy.resolveMediaTypes(null);

		assertThat(mediaTypes).isEqualTo(ContentNegotiationStrategy.MEDIA_TYPE_ALL_LIST);
	}

	@Test
	void resolveMediaTypesHandleNoMatch() throws Exception {
		Map<String, MediaType> mapping = null;
		TestMappingContentNegotiationStrategy strategy = new TestMappingContentNegotiationStrategy("xml", mapping);

		List<MediaType> mediaTypes = strategy.resolveMediaTypes(null);

		assertThat(mediaTypes).hasSize(1);
		assertThat(mediaTypes.get(0).toString()).isEqualTo("application/xml");
	}

	@Test
	void resolveMediaTypesHandleNoMatchAddsMappingForPlainExtension() throws Exception {
		Map<String, MediaType> mapping = Collections.singletonMap("json", MediaType.APPLICATION_JSON);
		TestMappingContentNegotiationStrategy strategy = new TestMappingContentNegotiationStrategy("xml", mapping);

		assertThat(strategy.resolveMediaTypes(null)).containsExactly(MediaType.APPLICATION_XML);
		assertThat(strategy.getMediaTypes()).containsOnlyKeys("json", "xml");
		assertThat(strategy.getAllFileExtensions()).containsExactlyInAnyOrder("json", "xml");
		assertThat(strategy.resolveFileExtensions(MediaType.APPLICATION_XML)).containsExactly("xml");
	}

	@Test
	void resolveMediaTypesViaFactoryDoesNotAddMappingForKeyWithDot() throws Exception {
		Map<String, MediaType> mapping = Collections.singletonMap("json", MediaType.APPLICATION_JSON);
		ParameterContentNegotiationStrategy strategy = new ParameterContentNegotiationStrategy(mapping);
		strategy.setUseRegisteredExtensionsOnly(false);

		for (int i = 0; i < 100; i++) {
			assertThat(strategy.resolveMediaTypes(createRequest("custom" + i + ".xml")))
					.containsExactly(MediaType.APPLICATION_XML);
		}
		assertThat(strategy.resolveMediaTypes(createRequest("not.json")))
				.containsExactly(MediaType.APPLICATION_JSON);

		assertThat(strategy.getMediaTypes()).containsOnlyKeys("json");
		assertThat(strategy.getAllFileExtensions()).containsExactly("json");
		assertThat(strategy.resolveFileExtensions(MediaType.APPLICATION_XML)).isEmpty();
		assertThat(strategy.resolveFileExtensions(MediaType.APPLICATION_JSON)).containsExactly("json");
	}

	@Test
	void resolveMediaTypesViaFactoryAddsSingleMappingForCaseVariants() throws Exception {
		Map<String, MediaType> mapping = Collections.singletonMap("json", MediaType.APPLICATION_JSON);
		ParameterContentNegotiationStrategy strategy = new ParameterContentNegotiationStrategy(mapping);
		strategy.setUseRegisteredExtensionsOnly(false);

		for (String key : new String[] {"XML", "Xml", "xMl", "xmL", "XmL", "xml"}) {
			assertThat(strategy.resolveMediaTypes(createRequest(key))).containsExactly(MediaType.APPLICATION_XML);
		}

		assertThat(strategy.getMediaTypes()).containsOnlyKeys("json", "xml");
		assertThat(strategy.getAllFileExtensions()).containsExactlyInAnyOrder("json", "xml");
		assertThat(strategy.resolveFileExtensions(MediaType.APPLICATION_XML)).containsExactly("xml");
	}

	@Test
	void resolveMediaTypesHandleNoMatchDoesNotAddMappingForNonExtensionKey() throws Exception {
		Map<String, MediaType> mapping = Collections.singletonMap("json", MediaType.APPLICATION_JSON);
		String[] keys = {"a.xml", "a/xml", "a\\xml", "../xml", "xml."};

		for (String key : keys) {
			AbstractMappingContentNegotiationStrategy strategy = new AbstractMappingContentNegotiationStrategy(mapping) {
				@Override
				protected String getMediaTypeKey(NativeWebRequest request) {
					return key;
				}
				@Override
				protected MediaType handleNoMatch(NativeWebRequest request, String mappingKey) {
					return MediaType.APPLICATION_XML;
				}
			};

			assertThat(strategy.resolveMediaTypes(null)).containsExactly(MediaType.APPLICATION_XML);
			assertThat(strategy.getMediaTypes()).as(key).containsOnlyKeys("json");
			assertThat(strategy.getAllFileExtensions()).as(key).containsExactly("json");
			assertThat(strategy.resolveFileExtensions(MediaType.APPLICATION_XML)).as(key).isEmpty();
		}
	}

	private static NativeWebRequest createRequest(String format) {
		MockHttpServletRequest request = new MockHttpServletRequest();
		request.addParameter("format", format);
		return new ServletWebRequest(request);
	}


	private static class TestMappingContentNegotiationStrategy extends AbstractMappingContentNegotiationStrategy {

		private final String extension;

		public TestMappingContentNegotiationStrategy(String extension, Map<String, MediaType> mapping) {
			super(mapping);
			this.extension = extension;
		}

		@Override
		protected String getMediaTypeKey(NativeWebRequest request) {
			return this.extension;
		}

		@Override
		protected MediaType handleNoMatch(NativeWebRequest request, String mappingKey) {
			return "xml".equals(mappingKey) ? MediaType.APPLICATION_XML : null;
		}
	}

}
